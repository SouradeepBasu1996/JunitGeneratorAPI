package com.online.shop.ShopOnline.entity;

import lombok.Getter;
import lombok.Setter;
import lombok.NoArgsConstructor;
import lombok.AllArgsConstructor;
import lombok.Builder;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "order")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Order{

    @Id
    private Long id;
    @Column(name ="product_name")
    private String productName;
    @Column(name ="product_id")
    private Long productId;
    @Column(name ="price")
    private Integer price;


}